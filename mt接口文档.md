## 美团点评POI搜索接口说明文档

接口鉴权
为了防止API调用过程中被黑客恶意篡改，调用任何一个API都需要携带签名，我方会根据请求参数，对签名进行验证，签名有效期默认为30分钟，签名不合法的请求将会被拒绝。

参数说明
参数	参数分类	备注
appkey	公共参数	三方标识
appsecrect	公共参数	三方秘钥
session	公共参数	授权码
注意:不同接口使用的授权码可能不同
timestamp	公共参数	时间戳，long，精确到毫秒
…params	业务参数	请求参数，可能多个
加签步骤：
 参数准备：按上述列出的参数（包括公共参数和业务参数，但除去appsecrect参数和值为空的参数），参数名先统一处理为小写；根据参数名的ASCII码表的正序排序；进行拼接,并在字符串前后加上appsecrect值。例如：a=1,b=2,ab=3，appsecrect=xyz排序并拼接后的结果为xyza1ab3b2xyz。
加密：对拼接后的字符串进行utf-8编码，并于编码后的进行md5加密，具体MD5加密算法以下线沟通为准。
将加密后的字节流采用16进制表示，并转换成小写，如：hex(“helloworld”.getBytes(“utf-8”)).toLowerCase()= “fc5e038d38a57032085441e7fe7010b0” 
接入指南
请求说明
接口	https://poiopen.dianping.com/router/poisearch/search
请求方式	post
请求说明	搜索附近POI
请求示例	{
“appkey”:”XXXX”,//见附录
“session”:”XXXXX”,//见附录
“timestamp”:”XXXX”,//精度毫秒，半小时内有效
“sign”:”XXXX”,//见方法签名计算方式
“keyword”:”XXXX”,
“latitude”:XXXX,
“longitude”:XXXX,
“mall”:1
}
入参
字段	类型	必填	备注
appkey	string	是	公共参数-三方标识
session	string	是	公共参数-授权码
timestamp	string	是	时间戳，long，精确到毫秒
sign	string	是	请求签名
keyword	string	否	搜索关键词
mall	int	否	1:只搜索商场,非必填,默认该过滤条件不生效
latitude	double	否	维度(GCJ-02),范围:-90.0d~90.0d
longitude	double	否	经度(GCJ-02),范围:-180.0d~180.0d
city	string	否	城市名,参考:查询授权城市列表
radius	int	否	搜索半径,默认1000米,最大限制5000米
categories	string	否	商户类目,逗号分隔”美食,亲子”。枚举值：{美食,K歌,购物,电影演出赛事,休闲娱乐,周边游,宴会,运动健身,丽人,结婚,酒店,爱车,亲子,学习培训,生活服务,医疗健康,家居,宠物,榛果民宿,交通枢纽}
page	int	否	页码,限制10以内,默认1
limit	int	否	单页返回条数,默认25
出参
字段	类型	备注
status	string	查询结果状态,OK:成功 其他:失败
message	string	查询失败原因
records	list	匹配poi列表
records.item.openshopid	string	开放平台商户ID
records.item.name	string	商户名
records.item.branchname	string	分店名
records.item.distance	double	商户距离（米），5000米以内展示（需申请权限）
records.item.shopaddress	string	商户地址 （需申请权限）
records.item.category	string	商户类目，如：美食 （需申请权限）
结果示例
{
    "records": [
        {
            "name": "龙之梦购物公园",
            "openshopid": "1IPcei6VQABtnzKwJ3pXvw"
        },
        {
            "name": "小马路商场",
            "openshopid": "PQl7VWSuABCYFPSQr_nYRQ"
        }
    ],
    "status": "OK",
    "total_count": 2
}

## 美团点评POI数据开放接口说明文档
支持三方进行设定范围内的POI扫描
支持三方获取指定POI（单一、批量）的相关信息
支持三方将POI信息同步到美团点评
支持POI信息变更实时通知

POI开放字段说明
字段	类型	备注
openshopid	string	商户唯一标识
openstatus	int	商户状态,0:下线 1:在线
highquality	int	高质量标志,1:高质 0:非高质
name	string	商户名
branch_name	string	分店名
address	string	地址
shopDesc	string	商户简介
city	string	城市
isOverseas	boolean	是否海外商户
latitude	double	维度
longitude	double	经度
telephone	string	电话号码(带区号)
business_hour	string	营业时间
categories	list	商户所属类别(叶子类目)
shopI18ns	list	商户多语言列表
shopI18ns.item.shopName	string	商户多语言商户名
shopI18ns.item.branchName	string	商户多语言分店名
shopI18ns.item.address	string	商户多语言地址
mShopInfoUrl	string	商户详情链接（h5）
appShopInfoUrl	string	商户详情链接（app）
evtShopInfoUrl	string	商户详情综链
pcShopInfoUrl	string	商户详情(PC)
wxShopInfoUrl	string	商户详情(微信小程序)
headPic	string	商户门头图
headPicVisible	int	商户门头图是否可用
reviewCount	int	评论总数
ugcs	list	评论列表
ugcs.item.nick	string	评论人昵称
ugcs.item.userface	string	评论人头像
ugcs.item.ispithy	boolean	是否优质评论
ugcs.item.score	float	评论星级(半星),0.0~5.0星
ugcs.item.star	int	评论星级(整星),0~5星
ugcs.item.content	string	评论内容
ugcs.item.photos	list	评论图片列表
ugcs.item.addtime	timestamp	评论时间
mReviewAllUrl	string	评论页URL(h5)
appReviewAllUrl	string	评论页URL(app)
reviewTags	list	评论标签
reviewTags.item.tag	string	评论标签名称
reviewTags.item.hit	int	评论标签命中次数
picCount	int	商户图片总数
shopPics	list	商户图片列表
shopPics.item.picUrl	string	图片链接
shopPics.item.title	string	图片标题
shopPics.item.addTime	string	图片添加时间
dishs	list	商户推荐菜列表
dishs.item.dishName	string	菜品名称
dishs.item.picUrl	string	菜品图片链接
dishs.item.price	double	菜品价格
dishs.item.recommendCount	int	菜品被推荐次数
mRecommendDishUrl	string	所有推荐菜页连接（h5）
appRecommendDishUrl	string	所有推荐菜页连接（app）
star	float	星级评分
avgprice	int	人均价格
special	list	商户特色服务
isBlackPearl	int	是否黑珍珠,1:是,0:否
takeawayable	boolean	是否支持外卖
takeawayinfo	obj	外卖详情
takeawayinfo.tag	string	外卖优惠短标题
takeawayinfo.longTag	string	外卖优惠短标题
takeawayinfo.url	string	外卖链接(app)
takeawayinfo.mUrl	string	外卖链接(h5)
queueable	boolean	是否支持排号
appQueueUrl	string	排号链接（app）
mQueueUrl	string	排号链接（h5）
bookable	string	是否支持预订
appBookURL	string	预订链接（app）
mBookURL	string	预订链接（h5）
mallInfo	obj	商场信息
mallInfo.popularShops	list	商场美食商户人气榜,openshopid列表
mallInfo.dzPopularShops	list	商场到综商户人气榜,openshopid列表
mallInfo.foodRankingListUrl	string	商场美食人气榜综链schema
mallInfo.mFoodRankingListUrl	string	商场美食人气榜跳转链接（h5）
mallInfo.appFoodRankingListUrl	string	商场美食人气榜schema（app）
mallInfo.floorGuideUrl	string	楼层导览综链schema
mallInfo.mFloorGuideUrl	string	楼层导览跳转链接（h5）
mallInfo.appFloorGuideUrl	string	楼层导览schema（app）
mallInfo.discount	boolean	商场是否有优惠信息
mallInfo.discountUrl	string	商场优惠信息页综链schema
mallInfo.mDiscountUrl	string	商场优惠信息页跳转链接（h5）
mallInfo.appDiscountUrl	string	商场优惠信息页schema（app）
mallInfo.foodListUrl	string	商场美食列表页schema
mallInfo.mallBaseInfoUrl	string	商场服务信息页综链schema
mallInfo.mMallBaseInfoUrl	string	商场服务信息页跳转链接（h5）
mallInfo.appMallBaseInfoUrl	string	商场服务信息页schema（app）
dealInfo	list	商场团单优惠信息
dealInfo.dealName	string	商场团单优惠名称
dealInfo.originPrice	double	原价
dealInfo.discountPrice	double	售价
dealInfo.dealPicUrl	string	团单头图
dealInfo.shopName	string	团单商户名称
dealInfo.type	int	团单类型：1-美食，2-到综
brandName	string	品牌名
接口鉴权
为了防止API调用过程中被黑客恶意篡改，调用任何一个API都需要携带签名，我方会根据请求参数，对签名进行验证，签名有效期默认为30分钟，签名不合法的请求将会被拒绝。

参数说明
参数	参数分类	备注
appkey	公共参数	三方标识
appsecrect	公共参数	三方秘钥
session	公共参数	授权码
注意:不同接口使用的授权码可能不同
timestamp	公共参数	时间戳，long，精确到毫秒
…params	业务参数	请求参数，可能多个
加签步骤：
 参数准备：按上述列出的参数（包括公共参数和业务参数，但除去appsecrect参数和值为空的参数），参数名先统一处理为小写；根据参数名的ASCII码表的正序排序；进行拼接,并在字符串前后加上appsecrect值。例如：a=1,b=2,ab=3，appsecrect=xyz排序并拼接后的结果为xyza1ab3b2xyz。
加密：对拼接后的字符串进行utf-8编码，并于编码后的进行md5加密，具体MD5加密算法以下线沟通为准。
将加密后的字节流采用16进制表示，并转换成小写，如：hex(“helloworld”.getBytes(“utf-8”)).toLowerCase()= “fc5e038d38a57032085441e7fe7010b0” 
获取授权开放城市
请求
接口	https://poiopen.dianping.com/router/city/opencity
请求方式	post
请求示例	{
“appkey”:”XXXX”,//见附录
“session”:”XXXXX”,//见附录
“timestamp”:”XXXX”,//精度毫秒，半小时内有效
“sign”:”XXXX”//见方法签名计算方式
}
结果示例
{
        "data": [
            "上海",
            "东京"
        ],
        "status": "success",
        "success": true
    }
分页查询指定城市POI列表
请求
接口	https://poiopen.dianping.com/router/poi/pagequerypoi
请求方式	post
请求示例	{
“appkey”:”XXXX”,//见附录
“session”:”XXXXX”,//见附录
“timestamp”:”XXXX”,//精度毫秒，半小时内有效
“sign”:”XXXX”,//见方法签名计算方式
“cityname”:”XXXX”,//指定城市
“page”:XXXX//指定页数
}
结果示例
{
    "data": {
        "currentPage": 1000,
        "pageSize": 100,
        "records": [
            {
                "address": "金张公路238号",
                "branch_name": "",
                "categories": [
                    "公司企业"
                ],
                "city": "上海",
                "latitude": 30.806003417969,
                "longitude": 121.28489149306,
                "name": "级工业园区·张堰工业区",
                "openshopid": "XXXX",
                "overseas": false,
                "telephone": ""
            },
            {
                "address": "康鸣路11号",
                "branch_name": "",
                "categories": [
                    "公司企业"
                ],
                "city": "上海",
                "latitude": 31.098248969184,
                "longitude": 121.31493299696,
                "name": "积旺工业园",
                "openshopid": "XXXX",
                "overseas": false,
                "telephone": ""
            }
        ],
        "totalHit": XXXX,
        "totalPage": XXXX
    },
    "status": "success",
    "success": true
}
查询指定POI信息
请求
接口	https://poiopen.dianping.com/router/poi/getsinglepoi
请求方式	post
请求示例	{
“appkey”:”XXXX”,//见附录
“session”:”XXXXX”,//见附录
“timestamp”:”XXXX”,//精度毫秒，半小时内有效
“sign”:”XXXX”,//见方法签名计算方式
“openshopid”:”XXXX”//指定商户
}
结果示例
{
    "data": {
        "address": "金张公路238号",
        "branch_name": "",
        "categories": [
            "公司企业"
        ],
        "city": "上海",
        "latitude": 30.806003417969,
        "longitude": 121.28489149306,
        "name": "级工业园区·张堰工业区",
        "overseas": false,
        "telephone": ""
    },
    "status": "success",
    "success": true
}
批量查询指定POI列表
请求
接口	https://poiopen.dianping.com/router/poi/batchgetpoi
请求方式	post
请求示例	{
“appkey”:”XXXX”,//见附录
“session”:”XXXX”,//见附录
“timestamp”:”XXXX”,//精度毫秒，半小时内有效
“sign”:”XXXX”,//见方法签名计算方法
“multiopenshopid”:”XXX,YYY”//最多100条,多个以逗号分隔
}
结果示例
{
    "data": {
        "XXXX": {
            "address": "金张公路238号",
            "branch_name": "",
            "categories": [
                "公司企业"
            ],
            "city": "上海",
            "latitude": 30.806003417969,
            "longitude": 121.28489149306,
            "name": "级工业园区·张堰工业区",
            "openshopid": "XXXX"
            "overseas": true,
            "telephone": ""
        }
    },
    "status": "success",
    "success": true
}
接收三方POI变更通知
请求
接口	https://poiopen.dianping.com/router/callback/notifychange
请求方式	post
请求示例	{
“appkey”:”XXXX”,//见附录
“session”:”XXXX”,//见附录
“timestamp”:”XXXX”,//精度毫秒，半小时内有效
“sign”:”XXXX”,//见方法签名计算方法
“outerpoiid”:”XXXX”,//三方POIID,必填
“city”:”XXXX”
}
结果示例
{
    "status":"success",
    "success":true
}

## 美团点评UGC数据开放接口说明文档

接口鉴权
为了防止API调用过程中被黑客恶意篡改，调用任何一个API都需要携带签名，我方会根据请求参数，对签名进行验证，签名有效期默认为30分钟，签名不合法的请求将会被拒绝。

参数说明
参数	参数分类	备注
appkey	公共参数	三方标识
appsecrect	公共参数	三方秘钥
session	公共参数	授权码
注意:不同接口使用的授权码可能不同
timestamp	公共参数	时间戳，long，精确到毫秒
…params	业务参数	请求参数，可能多个
提醒：content为上传的内容，数据较大，为保证加签效率，该字段不参与加签
加签步骤：
 参数准备：按上述列出的参数（包括公共参数和业务参数，但除去appsecrect参数和值为空的参数），参数名先统一处理为小写；根据参数名的ASCII码表的正序排序；进行拼接,并在字符串前后加上appsecrect值。例如：a=1,b=2,ab=3，appsecrect=xyz排序并拼接后的结果为xyza1ab3b2xyz。
加密：对拼接后的字符串进行utf-8编码，并于编码后的进行md5加密，具体MD5加密算法以下线沟通为准。
将加密后的字节流采用16进制表示，并转换成小写，如：hex(“helloworld”.getBytes(“utf-8”)).toLowerCase()= “fc5e038d38a57032085441e7fe7010b0” 
ugc上传接口
结构化类型说明
段落类型	子类型	说明
text	title	文章标题
text	author	作者
text	pubdate	发布时间
text	body	正文
text	userid	外源系统用户id
text	shopid	点评侧商户id
text	star	总评分
text	flavor	口味评分
text	environment	环境评分
text	service	服务评分
text	dishs	点赞菜名集合，以逗号分隔
pic	——	图片
video	——	视频
voice	——	音频
ugc内容样例
[
  {
    "type": "text",
    "subtype": "title",
    "content": "XXX（标题）"
  },
  {
    "type": "text",
    "subtype": "pubdate",
    "content": "XXX（发布时间）"
  },
  {
    "type": "text",
    "subtype": "author",
    "content": "XXX（作者）"
  },
  {
    "type": "text",
    "subtype": "body",
    "content": "XXX"
  },
  {
    "type": "video",
    "content": "URL（外源视频URL）"
  },
  {
    "type": "text",
    "subtype": "body",
    "content": "XXXX"
  },
  {
    "type": "pic",
    "content": "URL（外源图片URL)）"
  }
  ......
]
提醒：按ugc原始内容段落顺序进行数据元素排序
请求
接口	https://poiopen.dianping.com/router/ugc/upload
请求方式	post
请求示例	{
“appkey”:”XXXX”,//见附录
“session”:”XXXXX”,//见附录
“timestamp”:”XXXX”,//精度毫秒，半小时内有效
“sign”:”XXXX”,//见方法签名计算方式
“userid”:XXXX,//关联点评用户账号
“articleid”:”XXXX”,//外源文章Id
“content”:”XXXX”//UGC内容，结构参考ugc内容样例
}
结果示例
{
        "status": "success",
        "success": true
}


## 美团点评菜品数据开放接口说明文档

接口鉴权
为了防止API调用过程中被黑客恶意篡改，调用任何一个API都需要携带签名，我方会根据请求参数，对签名进行验证，签名有效期默认为30分钟，签名不合法的请求将会被拒绝。

参数说明
参数	参数分类	备注
appkey	公共参数	三方标识
appsecrect	公共参数	三方秘钥
session	公共参数	授权码
注意:不同接口使用的授权码可能不同
timestamp	公共参数	时间戳，long，精确到毫秒
…params	业务参数	请求参数，可能多个
加签步骤：
 参数准备：按上述列出的参数（包括公共参数和业务参数，但除去appsecrect参数和值为空的参数），参数名先统一处理为小写；根据参数名的ASCII码表的正序排序；进行拼接,并在字符串前后加上appsecrect值。例如：a=1,b=2,ab=3，appsecrect=xyz排序并拼接后的结果为xyza1ab3b2xyz。
加密：对拼接后的字符串进行utf-8编码，并于编码后的进行md5加密，具体MD5加密算法以下线沟通为准。
将加密后的字节流采用16进制表示，并转换成小写，如：hex(“helloworld”.getBytes(“utf-8”)).toLowerCase()= “fc5e038d38a57032085441e7fe7010b0” 
菜品榜单内容输出
请求
接口	https://poiopen.dianping.com/router/dish/dishlist
请求方式	post
请求示例	{
“appkey”:”XXXX”,//见附录
“session”:”XXXXX”,//见附录
“timestamp”:”XXXX”,//精度毫秒，半小时内有效
“sign”:”XXXX”,//见方法签名计算方式
“dishname”:”XXXX”,//菜品名称
“ip”:XXXX,//ip地址
}
结果示例
提醒：点评后端判断地理位置以及菜品名称能够有数据匹配，则传输当地该菜品餐厅排行榜单数据，返回字段中 type 为 1

{
    "data": {
        "dishVo": {
            "name": "XXX（菜品名称）",
            "picUrl": "首图URL，包含https://协议",
            "shopCount": X（菜品人气商户榜中商户数）,
            "showTags": [
                "XX",
                "XX",
                "XX"
            ], // 直达区显示标签
            "subTitle": "XXX（直达区副标题）",
            "tagsLineText": "XXXXX（标签行文案）"
        },
        "type": 1,
        "url": "URL（菜品详情页跳转链接）"
    },
    "status": "success",
    "success": true
}
提醒：如果点评后端没有响应的数据或者只能满足一项数据，则展示当地热搜列表数据，返回字段中 type 为 2

{
    "data": {
        "searchList": [
            {
                "keyword": "XXX（菜品名称）",
                "searchCount": XXX // 搜索热度
            },
            {
                "keyword": "XXX",
                "searchCount": XXX
            },
            {
                "keyword": "XXX",
                "searchCount": XXX
            }
            ......
        ],
        "type": 2,
        "url": "URL（热搜榜单详情页跳转链接）"
    },
    "status": "success",
    "success": true
}

## 美团点评实时数据开放接口说明文档

POI实时信息开放字段说明
字段	类型	备注
queueInfo	obj	POI实时排队信息
queueInfo.msg	string	POI实时排队说明
queueInfo.shortMsg	string	POI实时排队简短说明
接口鉴权
为了防止API调用过程中被黑客恶意篡改，调用任何一个API都需要携带签名，我方会根据请求参数，对签名进行验证，签名有效期默认为30分钟，签名不合法的请求将会被拒绝。

参数说明
参数	参数分类	备注
appkey	公共参数	三方标识
appsecrect	公共参数	三方秘钥
session	公共参数	授权码
注意:不同接口使用的授权码可能不同
timestamp	公共参数	时间戳，long，精确到毫秒
…params	业务参数	请求参数，可能多个
加签步骤：
 参数准备：按上述列出的参数（包括公共参数和业务参数，但除去appsecrect参数和值为空的参数），参数名先统一处理为小写；根据参数名的ASCII码表的正序排序；进行拼接,并在字符串前后加上appsecrect值。例如：a=1,b=2,ab=3，appsecrect=xyz排序并拼接后的结果为xyza1ab3b2xyz。
加密：对拼接后的字符串进行utf-8编码，并于编码后的进行md5加密，具体MD5加密算法以下线沟通为准。
将加密后的字节流采用16进制表示，并转换成小写，如：hex(“helloworld”.getBytes(“utf-8”)).toLowerCase()= “fc5e038d38a57032085441e7fe7010b0” 
POI合作信息实时查询
请求
接口	https://poiopen.dianping.com/router/realtime/getcoopinfo
请求方式	post
请求示例	{
“appkey”:”XXXX”,//见附录
“session”:”XXXXX”,//见附录
“timestamp”:”XXXX”,//精度毫秒，半小时内有效
“sign”:”XXXX”,//见方法签名计算方式
“openshopid”:”XXXX”,//POI标识
}
结果示例
{
    "data":{
        "queueInfo":{
            "msg":"当前无需排队",
            "shortMsg":"无需排队"
        }
    },
    "status":"success",
    "success":true
}
POI电话实时信息查询
请求
接口	https://poiopen.dianping.com/router/realtime/getpoiphone
请求方式	post
请求示例	{
“appkey”:”XXXX”,//见附录
“session”:”XXXXX”,//见附录
“timestamp”:”XXXX”,//精度毫秒，半小时内有效
“sign”:”XXXX”,//见方法签名计算方式
“userphone”:”XXXX”,// 准备呼叫商户的用户号码
}
结果示例
{
    "data":{
        "poiPhone":"13213212345"
    },
    "status":"success",
    "success":true
}

## 美团点评图像识别能力开放接口说明文档

接口鉴权
为了防止API调用过程中被黑客恶意篡改，调用任何一个API都需要携带签名，我方会根据请求参数，对签名进行验证，签名有效期默认为30分钟，签名不合法的请求将会被拒绝。

参数说明
参数	参数分类	备注
appkey	公共参数	三方标识
appsecrect	公共参数	三方秘钥
session	公共参数	授权码
注意:不同接口使用的授权码可能不同
timestamp	公共参数	时间戳，long，精确到毫秒
…params	业务参数	请求参数，可能多个
加签步骤：
 参数准备：按上述列出的参数（包括公共参数和业务参数，但除去appsecrect参数和值为空的参数），参数名先统一处理为小写；根据参数名的ASCII码表的正序排序；进行拼接,并在字符串前后加上appsecrect值。例如：a=1,b=2,ab=3，appsecrect=xyz排序并拼接后的结果为xyza1ab3b2xyz。
加密：对拼接后的字符串进行utf-8编码，并于编码后的进行md5加密，具体MD5加密算法以下线沟通为准。
将加密后的字节流采用16进制表示，并转换成小写，如：hex(“helloworld”.getBytes(“utf-8”)).toLowerCase()= “fc5e038d38a57032085441e7fe7010b0” 
拍照识店接口
入参说明
字段	类型	是否必填	备注
appkey	string	必填	三方标识
session	string	必填	接口授权码
sign	string	必填	请求签名
timestamp	string	必填	时间戳，long，精确到毫秒
imgdata	string	必填	图片url或图片字节流经过base64编码形成的字符串
图片长边不得大于1200，建议尺寸是图片长边为768
datatype	int	必填	数据输入类型:1.字节流 2.图片url
lat	double	必填	维度
lng	double	必填	经度
coordtype	int	必填	经纬度类型 1:GPS 2:GCJ02 3:MAPBAR 4:BAIDU
返回结果说明
字段	类型	备注
openShopId	string	商户标识,可通过开放平台接口查询商户详情
name	string	商户名
mShopInfoUrl	string	商户详情页h5链接
appShopInfoUrl	string	商户详情页点评App链接
请求
接口	https://poiopen.dianping.com/router/imagerecognition/querypoi
请求方式	post
请求示例	{
“session”: “XXXX”,
“sign”: “XXXX”,
“appkey”: “XXXX”,
“imgdata”: “XXXX”,
“timestamp”: “XXXX”,
“datatype”:2,
“lng”:121.420041,
“lat”:31.215691,
“coordtype”:1
}
结果示例
提醒：识别结果为多个时,按置信度倒序输出

{
  "data": {
    "predictShopName": [
      "大江戶温泉物語"
    ],
    "predictShops": [
      {
        "appShopInfoUrl": "dianping://shopinfo?id=69647293&utm_source=poiopen&utm_medium=&utm_campaign=appshxq",
        "mShopInfoUrl": "https://m.dianping.com/shop/69647293?utm_source=poiopen&utm_medium=&utm_campaign=mshxq",
        "name": "大江户温泉物语",
        "openShopId": "EdmOL2GH-iwbNDKn1ZBtXA"
      }
    ]
  },
  "status": "success",
  "success": true
}
拍照识菜接口
入参说明
字段	类型	是否必填	备注
appkey	string	必填	三方标识
session	string	必填	接口授权码
sign	string	必填	请求签名
timestamp	string	必填	时间戳，long，精确到毫秒
imgdata	string	必填	图片url或图片字节流经过base64编码形成的字符串
datatype	int	必填	数据输入类型:1.字节流 2.图片url
sputype	int	非必填	spu类型 1:菜品,默认为1
返回结果说明
字段	类型	备注
name	string	菜名
请求
接口	https://poiopen.dianping.com/router/imagerecognition/queryspu
请求方式	post
请求示例	{
“session”: “XXXX”,
“sign”: “XXXX”,
“appkey”: “XXXX”,
“imgdata”: “https://ss0.bdstatic.com/70cFvHSh_Q1YnxGkpoWK1HF6hhy/it/u=27632446,1836274589&fm=27&gp=0.jpg“,
“timestamp”: “XXXX”,
“datatype”:2,
“sputype”:1
}
结果示例
提醒：识别结果为多个时,按置信度倒序输出

{
    "data": [
        {
            "name": "猪肉脯"
        },
        {
            "name": "猪肉干"
        },
        {
            "name": "肉干"
        },
        {
            "name": "碳烤肉"
        },
        {
            "name": "猪肉片"
        },
        {
            "name": "薄饼"
        },
        {
            "name": "碳烤猪颈肉"
        },
        {
            "name": "辣条"
        },
        {
            "name": "烤肉"
        },
        {
            "name": "山楂糕"
        },
        {
            "name": "烤猪肉"
        },
        {
            "name": "酱肉"
        },
        {
            "name": "烤猪皮"
        },
        {
            "name": "素肉"
        },
        {
            "name": "孜然肉"
        },
        {
            "name": "烤培根"
        },
        {
            "name": "麻辣肉片"
        }
    ],
    "status": "success",
    "success": true
}

## 美团点评公共交通数据开放接口说明文档

接口鉴权
为了防止API调用过程中被黑客恶意篡改，调用任何一个API都需要携带签名，我方会根据请求参数，对签名进行验证，签名有效期默认为30分钟，签名不合法的请求将会被拒绝。

参数说明
参数	参数分类	备注
appkey	公共参数	三方标识
appsecrect	公共参数	三方秘钥
session	公共参数	授权码
注意:不同接口使用的授权码可能不同
timestamp	公共参数	时间戳，long，精确到毫秒
…params	业务参数	请求参数，可能多个
加签步骤：
参数准备：按上述列出的参数（包括公共参数和业务参数，但除去appsecrect参数和值为空的参数），参数名先统一处理为小写；根据参数名的ASCII码表的正序排序；进行拼接,并在字符串前后加上appsecrect值。例如：a=1,b=2,ab=3，appsecrect=xyz排序并拼接后的结果为xyza1ab3b2xyz。
加密：对拼接后的字符串进行utf-8编码，并于编码后的进行md5加密，具体MD5加密算法以下线沟通为准。
将加密后的字节流采用16进制表示，并转换成小写，如：hex(“helloworld”.getBytes(“utf-8”)).toLowerCase()= “fc5e038d38a57032085441e7fe7010b0”

接入指南
请求说明
接口	https://poiopen.dianping.com/router/s3/getpublictransit
请求方式	post
请求说明	获取公交数据的下载链接,下载链接有效期15分钟
请求示例	{
“appkey”:”XXXX”,//见附录
“session”:”XXXXX”,//见附录
“timestamp”:”XXXX”,//精度毫秒，半小时内有效
“sign”:”XXXX”,//见方法签名计算方式
“version”:”XXXX”
}
入参
字段	类型	必填	备注
version	string	否	数据版本(缺省是今天的日期)，格式yyyyMMdd
出参
字段	类型	备注
lastVersion	string	查询到的数据版本
line	list	公交路线下载Url列表
stop	list	公交站点下载Url列表
station	list	公交站台下载Url列表
exit	list	地铁出入口下载Url列表
结果示例
{
  "data": {
    "lastVersion":"20241018",
    "line": [
        "https://line_url0",
        "https://line_url1",
        "https://line_url2",
        "https://line_url3"
    ],
    "stop": [
      "https://stop_url0",
      "https://stop_url1",
      "https://stop_url2",
      "https://stop_url3"
    ],
    "station": [
      "https://station_url0",
      "https://station_url1",
      "https://station_url2",
      "https://station_url3"
    ],
    "exit": [
      "https://exit_url0",
      "https://exit_url1",
      "https://exit_url2",
      "https://exit_url3"
    ]
  },
  "status": "success",
  "success": true
}

